import asyncio, threading, time, json
import uvicorn
from fastapi import FastAPI, Request
from app.queue import ingest_update

app = FastAPI(title="EA OS Webhook Gateway")

@app.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    """Listens for payment/Stripe webhooks and queues them for processing."""
    try:
        payload = await request.json()
        print(f"💰 API [Stripe]: Received payment webhook.", flush=True)
        # Drop directly into the Postgres tg_updates queue
        ingest_update(tenant="ea_bot", update_id=int(time.time()*1000), payload={"text": f"Payment Webhook Received: {json.dumps(payload)}"})
        return {"status": "success", "queued": True}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/health")
async def health_check():
    return {"status": "online", "role": "ea-api"}

def _start_uvicorn():
    uvicorn.run(app, host="0.0.0.0", port=8090, log_level="warning")

async def run_api():
    print("==================================================", flush=True)
    print("🌐 EA OS API: ONLINE (Listening on Port 8090...)", flush=True)
    print("==================================================", flush=True)
    
    # Run Uvicorn in a background thread so it doesn't block the async loop
    server_thread = threading.Thread(target=_start_uvicorn, daemon=True)
    server_thread.start()
    
    while True:
        await asyncio.sleep(3600)
