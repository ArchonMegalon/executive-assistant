import asyncio, json, traceback, time, os
from app.telegram import TelegramClient
from app.settings import settings
from app.queue import ingest_update
import app.poll_listener as pl

def _atomic_write_offset(offset: int):
    path = "/attachments/tg_offset.json"
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"offset": offset}, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception: pass

async def run_poller():
    print("==================================================", flush=True)
    print("📡 EA OS POLLER: ONLINE (Listening to Telegram...)", flush=True)
    print("==================================================", flush=True)
    if not settings.telegram_bot_token: return
    tg = TelegramClient(settings.telegram_bot_token)
    
    # Keeps the watchdog thread from killing us
    asyncio.create_task(pl.heartbeat_pinger())
    
    offset = 0
    try:
        with open("/attachments/tg_offset.json", "r") as f: offset = json.load(f).get("offset", 0)
    except: pass
    
    while True:
        try:
            updates = await tg.get_updates(offset, timeout_s=30)
            for u in updates:
                update_id = u['update_id']
                offset = max(offset, update_id + 1)
                await asyncio.to_thread(_atomic_write_offset, offset)
                
                tenant = "ea_bot"
                chat_id = None
                if 'message' in u:
                    chat_id = u['message'].get('chat', {}).get('id')
                elif 'callback_query' in u:
                    chat_id = u['callback_query'].get('message', {}).get('chat', {}).get('id')
                elif 'channel_post' in u:
                    chat_id = u['channel_post'].get('chat', {}).get('id')
                elif 'edited_channel_post' in u:
                    chat_id = u['edited_channel_post'].get('chat', {}).get('id')
                if chat_id: tenant = f"chat_{chat_id}"
                
                # Throw it instantly into the immortal Postgres Queue
                await asyncio.to_thread(ingest_update, tenant=tenant, update_id=update_id, payload=u)
                print(f"📥 Poller: Ingested update {update_id} into DB.", flush=True)
        except Exception as e:
            print(f"🚨 POLLER ERROR: {e}", flush=True)
            await asyncio.sleep(5)
