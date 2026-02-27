import asyncio, httpx, os
from app.db import get_db
from app.settings import TELEGRAM_BOT_TOKEN, EA_ATTACHMENTS_DIR

async def run_outbox():
    print("==================================================", flush=True)
    print("📤 EA OS OUTBOX SENDER: ONLINE & POLLING", flush=True)
    print("==================================================", flush=True)
    
    db = get_db()
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            try:
                row = await asyncio.to_thread(db.fetchone, """
                    UPDATE tg_outbox 
                    SET status = 'processing', updated_at = NOW() 
                    WHERE id = (
                        SELECT id FROM tg_outbox 
                        WHERE status IN ('queued', 'retry') AND next_attempt_at <= NOW() 
                        ORDER BY created_at ASC FOR UPDATE SKIP LOCKED LIMIT 1
                    ) RETURNING *;
                """)
                
                if not row:
                    await asyncio.sleep(2)
                    continue
                
                outbox_id, chat_id, payload, attempts = row['id'], row['chat_id'], row['payload_json'], row['attempt_count'] + 1
                
                try:
                    if payload.get("type") == "photo" and "artifact_id" in payload:
                        photo_path = os.path.join(EA_ATTACHMENTS_DIR, "artifacts", f"{payload['artifact_id']}.png")
                        if not os.path.exists(photo_path): raise Exception(f"Artifact {photo_path} not found")
                        
                        with open(photo_path, "rb") as f:
                            data = {"chat_id": chat_id, "parse_mode": payload.get("parse_mode", "HTML")}
                            if "caption" in payload: data["caption"] = payload["caption"]
                            res = await client.post(f"{api_url}/sendPhoto", data=data, files={"photo": f})
                    else:
                        tg_payload = {"chat_id": chat_id, "text": payload.get("text", "Empty msg"), "parse_mode": payload.get("parse_mode", "HTML")}
                        res = await client.post(f"{api_url}/sendMessage", json=tg_payload)

                    if res.status_code == 200:
                        await asyncio.to_thread(db.execute, "UPDATE tg_outbox SET status = 'sent', updated_at = NOW() WHERE id = %s", (outbox_id,))
                        print(f"✅ Outbox sent message {outbox_id}", flush=True)
                    elif res.status_code == 429:
                        retry_after = res.json().get("parameters", {}).get("retry_after", 30)
                        await asyncio.to_thread(db.execute, "UPDATE tg_outbox SET status = 'retry', attempt_count = %s, next_attempt_at = NOW() + interval '%s seconds', last_error = 'HTTP 429', updated_at = NOW() WHERE id = %s", (attempts, retry_after, outbox_id))
                        print(f"⚠️ Telegram 429 Rate Limit. Backing off for {retry_after}s.", flush=True)
                    else:
                        await asyncio.to_thread(db.execute, "UPDATE tg_outbox SET status = 'failed', last_error = %s, attempt_count = %s, updated_at = NOW() WHERE id = %s", (res.text, attempts, outbox_id))

                except Exception as e:
                    await asyncio.to_thread(db.execute, "UPDATE tg_outbox SET status = 'retry', attempt_count = %s, next_attempt_at = NOW() + interval '30 seconds', last_error = %s, updated_at = NOW() WHERE id = %s", (attempts, str(e), outbox_id))
                    
                await asyncio.sleep(0.1)
            except Exception as e:
                print(f"🚨 Outbox Queue Error: {e}", flush=True)
                await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(run_outbox())
