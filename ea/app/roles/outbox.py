import asyncio, traceback
from app.queue import claim_outbox_message, mark_outbox_sent, mark_outbox_error
from app.telegram import TelegramClient
from app.settings import settings

async def run_outbox():
    print("==================================================", flush=True)
    print("📤 EA OS OUTBOX: ONLINE (Routing to Telegram...)", flush=True)
    print("==================================================", flush=True)
    
    if not settings.telegram_bot_token:
        print("🚨 OUTBOX FATAL: No Telegram Token found.", flush=True)
        return
        
    tg = TelegramClient(settings.telegram_bot_token)
    
    while True:
        msg = None
        try:
            msg = await asyncio.to_thread(claim_outbox_message)
            if not msg:
                await asyncio.sleep(0.5)
                continue
                
            payload = msg.get("payload_json", {})
            text = payload.get("text", "")
            
            print(f"📤 Outbox: Sending message {msg['id']} to Chat {msg['chat_id']}...", flush=True)
            
            # Execute actual Telegram send
            await tg.send_message(
                chat_id=msg["chat_id"], 
                text=text, 
                parse_mode=payload.get("parse_mode", "HTML")
            )
            
            await asyncio.to_thread(mark_outbox_sent, message_id=msg["id"])
            print(f"✅ Outbox: Message {msg['id']} delivered.", flush=True)
            
        except Exception as e:
            print(f"🚨 OUTBOX ERROR: {e}", flush=True)
            if msg: 
                try: await asyncio.to_thread(mark_outbox_error, message_id=msg["id"], attempt_count=msg.get("attempt_count", 0), error=str(e))
                except: pass
            await asyncio.sleep(5)
