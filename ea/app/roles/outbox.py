import asyncio, httpx, os, json, re
from app.db import get_db
from app.settings import TELEGRAM_BOT_TOKEN, EA_ATTACHMENTS_DIR, settings


def _strip_telegram_html(text: str) -> str:
    raw = str(text or "")
    no_tags = re.sub(r"</?[^>]+>", "", raw)
    return no_tags.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def _is_telegram_entity_parse_error(status_code: int, body: str) -> bool:
    if int(status_code) != 400:
        return False
    lowered = str(body or "").lower()
    return "can't parse entities" in lowered or "unsupported start tag" in lowered


def _activate_delivery_session(db, session_id: int) -> None:
    window_sec = max(60, int(getattr(settings, "avomap_late_attach_window_sec", 900) or 900))
    db.execute(
        """
        UPDATE delivery_sessions
        SET status='active',
            enhancement_deadline_ts=NOW() + (%s * INTERVAL '1 second')
        WHERE session_id=%s
        """,
        (window_sec, int(session_id)),
    )


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
                            parse_mode = payload.get("parse_mode", "HTML")
                            data = {"chat_id": chat_id, "parse_mode": parse_mode}
                            if "caption" in payload: data["caption"] = payload["caption"]
                            if "reply_markup" in payload: data["reply_markup"] = json.dumps(payload["reply_markup"])
                            res = await client.post(f"{api_url}/sendPhoto", data=data, files={"photo": f})
                            if _is_telegram_entity_parse_error(res.status_code, res.text):
                                f.seek(0)
                                retry_data = {"chat_id": chat_id}
                                if "caption" in payload:
                                    retry_data["caption"] = _strip_telegram_html(payload.get("caption", ""))
                                if "reply_markup" in payload:
                                    retry_data["reply_markup"] = json.dumps(payload["reply_markup"])
                                res = await client.post(f"{api_url}/sendPhoto", data=retry_data, files={"photo": f})
                    else:
                        parse_mode = payload.get("parse_mode", "HTML")
                        tg_payload = {"chat_id": chat_id, "text": payload.get("text", "Empty msg"), "parse_mode": parse_mode}
                        if "reply_markup" in payload: tg_payload["reply_markup"] = payload["reply_markup"]
                        res = await client.post(f"{api_url}/sendMessage", json=tg_payload)
                        if _is_telegram_entity_parse_error(res.status_code, res.text):
                            retry_payload = {"chat_id": chat_id, "text": _strip_telegram_html(payload.get("text", "Empty msg"))}
                            if "reply_markup" in payload:
                                retry_payload["reply_markup"] = payload["reply_markup"]
                            res = await client.post(f"{api_url}/sendMessage", json=retry_payload)

                    if res.status_code == 200:
                        await asyncio.to_thread(db.execute, "UPDATE tg_outbox SET status = 'sent', updated_at = NOW() WHERE id = %s", (outbox_id,))
                        session_id = payload.get("delivery_session_id")
                        if session_id is not None:
                            try:
                                await asyncio.to_thread(_activate_delivery_session, db, int(session_id))
                            except Exception:
                                pass
                        print(f"✅ Outbox sent message {outbox_id}", flush=True)
                    elif res.status_code == 429:
                        retry_after = res.json().get("parameters", {}).get("retry_after", 30)
                        await asyncio.to_thread(
                            db.execute,
                            "UPDATE tg_outbox SET status = 'retry', attempt_count = %s, next_attempt_at = NOW() + (%s * INTERVAL '1 second'), last_error = 'HTTP 429', updated_at = NOW() WHERE id = %s",
                            (attempts, int(retry_after), outbox_id),
                        )
                        print(f"⚠️ Telegram 429 Rate Limit. Backing off for {retry_after}s.", flush=True)
                    else:
                        await asyncio.to_thread(db.execute, "UPDATE tg_outbox SET status = 'failed', last_error = %s, attempt_count = %s, updated_at = NOW() WHERE id = %s", (res.text, attempts, outbox_id))

                except Exception as e:
                    await asyncio.to_thread(
                        db.execute,
                        "UPDATE tg_outbox SET status = 'retry', attempt_count = %s, next_attempt_at = NOW() + (%s * INTERVAL '1 second'), last_error = %s, updated_at = NOW() WHERE id = %s",
                        (attempts, 30, str(e), outbox_id),
                    )
                    
                await asyncio.sleep(0.1)
            except Exception as e:
                print(f"🚨 Outbox Queue Error: {e}", flush=True)
                await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(run_outbox())
