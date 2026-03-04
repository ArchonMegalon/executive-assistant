import asyncio, traceback, time, os
from app.repair.engine import process_repair_jobs
from app.queue import claim_update, mark_update_done, mark_update_error
import app.poll_listener as pl

async def _route_update(u_data):
    if 'callback_query' in u_data:
        await pl.handle_callback(u_data['callback_query'])
        return

    msg = None
    if 'message' in u_data:
        msg = u_data['message']
    elif 'channel_post' in u_data:
        msg = u_data['channel_post']
    elif 'edited_channel_post' in u_data:
        msg = u_data['edited_channel_post']
    if not msg:
        return

    chat_id = msg.get('chat', {}).get('id')
    if not chat_id:
        return
    cmd_text = str(msg.get('text') or msg.get('caption') or "").strip()
    if cmd_text.startswith('/'):
        await pl.handle_command(chat_id, cmd_text, msg)
    elif msg.get('text') or msg.get('photo') or msg.get('document') or msg.get('voice') or msg.get('audio'):
        await pl.handle_intent(chat_id, msg)

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
            await asyncio.wait_for(_route_update(job["payload_json"]), timeout=240.0)
            
            await asyncio.to_thread(mark_update_done, tenant=job["tenant"], update_id=job["update_id"])
            print(f"✅ Worker: Job {job['update_id']} finished and committed.", flush=True)
            
        except Exception as e:
            print(f"🚨 WORKER ERROR: {traceback.format_exc()}", flush=True)
            if job:
                try: await asyncio.to_thread(mark_update_error, tenant=job["tenant"], update_id=job["update_id"], attempt_count=job["attempt_count"], error=str(e))
                except: pass
            await asyncio.sleep(1)
