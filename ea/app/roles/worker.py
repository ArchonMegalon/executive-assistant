import asyncio, traceback, time, os
from app.repair.engine import process_repair_jobs
from app.queue import claim_update, mark_update_done, mark_update_error
import app.poll_listener as pl
from app.update_router import route_update

async def run_worker():
    print("==================================================", flush=True)
    print("🧠 EA OS WORKER: ONLINE (Processing Postgres Inbox)", flush=True)
    print("==================================================", flush=True)
    
    # Keeps the watchdog thread from killing us
    asyncio.create_task(pl.heartbeat_pinger())
    
    next_repair_tick = 0.0
    while True:
        now = time.time()
        if now >= next_repair_tick:
            try:
                await asyncio.to_thread(process_repair_jobs, 4)
            except Exception:
                pass
            next_repair_tick = now + max(2.0, float(os.getenv("EA_MUM_BRAIN_TICK_SEC", "5")))

        job = None
        try:
            job = await asyncio.to_thread(claim_update)
            if not job:
                await asyncio.sleep(0.5)
                continue
            
            print(f"⚙️ Worker: Claimed job {job['update_id']}! Executing...", flush=True)
            
            # Execute your existing monolithic processing logic safely!
            await asyncio.wait_for(
                route_update(
                    job["payload_json"],
                    on_callback=pl.handle_callback,
                    on_command=pl.handle_command,
                    on_intent=pl.handle_intent,
                ),
                timeout=240.0,
            )
            
            await asyncio.to_thread(mark_update_done, tenant=job["tenant"], update_id=job["update_id"])
            print(f"✅ Worker: Job {job['update_id']} finished and committed.", flush=True)
            
        except Exception as e:
            print(f"🚨 WORKER ERROR: {traceback.format_exc()}", flush=True)
            if job:
                try: await asyncio.to_thread(mark_update_error, tenant=job["tenant"], update_id=job["update_id"], attempt_count=job["attempt_count"], error=str(e))
                except: pass
            await asyncio.sleep(1)
